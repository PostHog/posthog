import { Transform } from 'stream'
import express, { NextFunction, Request, RequestHandler, Response } from 'ultimate-express'
import { createBrotliDecompress, createGunzip, createInflate } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

function decompressorFor(encoding: string): (() => Transform) | undefined {
    switch (encoding) {
        case 'gzip':
            return createGunzip
        case 'deflate':
            return createInflate
        case 'br':
            return createBrotliDecompress
        default:
            return undefined
    }
}

export function bytesParserLimit(limitBytes: number): string {
    return String(limitBytes)
}

function contentEncodingOf(req: Request): string {
    return (req.headers['content-encoding'] ?? '').trim().toLowerCase() || 'identity'
}

const JSON_MEDIA_TYPE = 'application/json'
const TEXT_MEDIA_TYPE = 'text/plain'
const TEXT_CHARSETS = new Set(['utf-8', 'utf-16le', 'latin1'])
const DEFAULT_TEXT_PARSER_LIMIT_BYTES = 100 * 1024

function mediaTypeOf(req: Request): string {
    return (req.headers['content-type'] ?? '').split(';')[0]
}

function charsetOf(req: Request): string {
    const contentType = req.headers['content-type'] ?? ''
    const charsetIndex = contentType.indexOf('charset=')
    if (charsetIndex === -1) {
        return 'utf-8'
    }
    return contentType
        .substring(charsetIndex + 'charset='.length)
        .split(';')[0]
        .trim()
        .toLowerCase()
}

const BODY_READING_METHODS = new Set(['POST', 'PUT', 'PATCH'])

function readsBody(req: Request): boolean {
    const extraBodyMethods: string[] | undefined = req.app.get('body methods')
    return BODY_READING_METHODS.has(req.method) || (extraBodyMethods?.includes(req.method) ?? false)
}

type BodyState = Request & { bodyRead?: boolean; rawBody?: string }

function tooLarge(): Error {
    return Object.assign(new Error('Request entity too large'), { status: 413 })
}

function refuse(res: Response, status: number, error: string): void {
    res.status(status).json({ status: 'error', error })
}

type Decoded = { ok: true; bytes: Buffer } | { ok: false; status: 400 | 413 }

type UwsBackedRequest = Request & { _res: { pause(): void; resume(): void } }
type AbortableResponse = Response & { aborted?: boolean }

function readDecoded(
    req: Request,
    res: Response,
    createDecompressor: () => Transform,
    limitBytes: number
): Promise<Decoded> {
    ;(req as BodyState).bodyRead = true
    return new Promise((resolve) => {
        const decompressor = createDecompressor()
        const transport = (req as UwsBackedRequest)._res
        const decoded: Buffer[] = []
        let decodedBytes = 0
        let receivedBytes = 0
        let decodingEnded = false
        let requestEnded = false
        let paused = false
        let settled = false
        const pause = (): void => {
            if (!paused) {
                paused = true
                req.pause()
                transport.pause()
            }
        }
        const resume = (): void => {
            if (paused && !(res as AbortableResponse).aborted) {
                paused = false
                transport.resume()
                req.resume()
            }
        }
        const settle = (result: Decoded): void => {
            if (!settled) {
                settled = true
                resume()
                decompressor.destroy()
                resolve(result)
            }
        }
        const succeedOnceBothEnd = (): void => {
            if (decodingEnded && requestEnded) {
                settle({ ok: true, bytes: Buffer.concat(decoded) })
            }
        }
        decompressor.on('data', (chunk: Buffer) => {
            decodedBytes += chunk.length
            if (decodedBytes > limitBytes) {
                return settle({ ok: false, status: 413 })
            }
            decoded.push(chunk)
        })
        decompressor.on('drain', resume)
        decompressor.on('error', () => settle({ ok: false, status: 400 }))
        decompressor.on('end', () => {
            decodingEnded = true
            succeedOnceBothEnd()
        })
        req.on('data', (chunk: Buffer) => {
            receivedBytes += chunk.length
            if (!settled && !decodingEnded && !decompressor.write(chunk)) {
                pause()
            }
        })
        req.on('end', () => {
            requestEnded = true
            if (receivedBytes === 0) {
                return settle({ ok: true, bytes: Buffer.alloc(0) })
            }
            if (!settled && !decodingEnded) {
                decompressor.end()
            }
            succeedOnceBothEnd()
        })
        req.on('error', () => settle({ ok: false, status: 400 }))
    })
}

export function createCompressedBodyMiddleware(limitBytes: number): RequestHandler {
    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = contentEncodingOf(req)
        if (encoding === 'identity' || !readsBody(req)) {
            return next()
        }
        const isJson = mediaTypeOf(req) === JSON_MEDIA_TYPE
        if (isJson && Number(req.headers['content-length'] ?? 0) > limitBytes) {
            return next(tooLarge())
        }
        const createDecompressor = decompressorFor(encoding)
        req.body = {}
        if (!isJson || !createDecompressor || req.headers['content-length'] === '0') {
            ;(req as BodyState).bodyRead = true
            return next()
        }
        readDecoded(req, res, createDecompressor, limitBytes)
            .then((decoded) => {
                if (!decoded.ok) {
                    return decoded.status === 413 ? next(tooLarge()) : refuse(res, 400, 'Malformed compressed body')
                }
                const text = decoded.bytes.toString('utf8')
                ;(req as BodyState).rawBody = text
                req.body = text.length === 0 ? {} : parseJSON(text)
                next()
            })
            .catch(next)
    }
}

export function createTextBodyParser(): RequestHandler {
    const parseIdentityText = express.text()

    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = contentEncodingOf(req)
        if (encoding === 'identity') {
            return parseIdentityText(req, res, next)
        }
        if (req.body === undefined) {
            req.body = {}
        }
        if (mediaTypeOf(req) !== TEXT_MEDIA_TYPE || req.headers['content-length'] === '0' || !readsBody(req)) {
            return next()
        }
        const createDecompressor = decompressorFor(encoding)
        if (!createDecompressor) {
            return refuse(res, 415, 'Unsupported content encoding')
        }
        if (Number(req.headers['content-length'] ?? 0) > DEFAULT_TEXT_PARSER_LIMIT_BYTES) {
            return refuse(res, 413, 'Request entity too large')
        }
        readDecoded(req, res, createDecompressor, DEFAULT_TEXT_PARSER_LIMIT_BYTES)
            .then((decoded) => {
                if (!decoded.ok) {
                    return decoded.status === 413
                        ? refuse(res, 413, 'Request entity too large')
                        : refuse(res, 400, 'Malformed compressed body')
                }
                const charset = charsetOf(req)
                if (!TEXT_CHARSETS.has(charset)) {
                    return refuse(res, 415, 'Unsupported charset')
                }
                req.body = decoded.bytes.toString(charset as BufferEncoding)
                next()
            })
            .catch(next)
    }
}
