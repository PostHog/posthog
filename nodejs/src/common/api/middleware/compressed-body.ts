import express, { NextFunction, Request, RequestHandler, Response } from 'ultimate-express'
import { brotliDecompress, gunzip, inflate } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

type Decompress = (input: Buffer, maxOutputLength: number) => Promise<Buffer>
type ZlibCall = (
    input: Buffer,
    options: { maxOutputLength: number },
    callback: (error: Error | null, result: Buffer) => void
) => void

const promised =
    (decompress: ZlibCall): Decompress =>
    (input, maxOutputLength) =>
        new Promise((resolve, reject) =>
            decompress(input, { maxOutputLength }, (error, result) => (error ? reject(error) : resolve(result)))
        )

const gunzipAsync = promised(gunzip)
const inflateAsync = promised(inflate)
const brotliDecompressAsync = promised(brotliDecompress)

function decompressorFor(encoding: string): Decompress | undefined {
    switch (encoding) {
        case 'gzip':
            return gunzipAsync
        case 'deflate':
            return inflateAsync
        case 'br':
            return brotliDecompressAsync
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
const MAX_COMPRESSED_TEXT_BYTES = 2 * DEFAULT_TEXT_PARSER_LIMIT_BYTES

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

function onceOnly(callback: (error?: unknown) => void): (error?: unknown) => void {
    let called = false
    return (error) => {
        if (!called) {
            called = true
            callback(error)
        }
    }
}

type Decoded = { ok: true; bytes: Buffer } | { ok: false; status: 400 | 413 }

function readCompressedBody(
    limitBytes: number,
    decodedLimitBytes: number
): (req: Request, res: Response, done: (error: unknown, decoded?: Decoded) => void) => void {
    const readRawBody = express.raw({ type: () => true, inflate: false, limit: bytesParserLimit(limitBytes) })
    return (req, res, done) => {
        ;(req as BodyState).bodyRead = false
        readRawBody(
            req,
            res,
            onceOnly((readError) => {
                if (readError) {
                    return done(readError)
                }
                const compressed: unknown = req.body
                req.body = {}
                if (!Buffer.isBuffer(compressed) || compressed.length === 0) {
                    return done(undefined, { ok: true, bytes: Buffer.alloc(0) })
                }
                decompressorFor(contentEncodingOf(req))!(compressed, decodedLimitBytes).then(
                    (bytes) => done(undefined, { ok: true, bytes }),
                    (error: NodeJS.ErrnoException) =>
                        done(undefined, { ok: false, status: error.code === 'ERR_BUFFER_TOO_LARGE' ? 413 : 400 })
                )
            })
        )
    }
}

export function createCompressedBodyMiddleware(limitBytes: number): RequestHandler {
    const readBody = readCompressedBody(limitBytes, limitBytes)

    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = contentEncodingOf(req)
        if (encoding === 'identity' || !readsBody(req)) {
            return next()
        }
        if (mediaTypeOf(req) !== JSON_MEDIA_TYPE) {
            req.body = {}
            ;(req as BodyState).bodyRead = true
            return next()
        }
        if (!decompressorFor(encoding)) {
            return refuse(res, 415, 'Unsupported content encoding')
        }
        readBody(req, res, (error, decoded) => {
            try {
                if (error) {
                    return next(error)
                }
                if (!decoded!.ok) {
                    return decoded!.status === 413 ? next(tooLarge()) : refuse(res, 400, 'Malformed compressed body')
                }
                if (decoded!.bytes.length === 0) {
                    return next()
                }
                const text = decoded!.bytes.toString('utf8')
                ;(req as BodyState).rawBody = text
                req.body = parseJSON(text)
                next()
            } catch (parseError) {
                next(parseError)
            }
        })
    }
}

export function createTextBodyParser(): RequestHandler {
    const parseIdentityText = express.text()
    const readBody = readCompressedBody(MAX_COMPRESSED_TEXT_BYTES, DEFAULT_TEXT_PARSER_LIMIT_BYTES)

    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = contentEncodingOf(req)
        if (encoding === 'identity') {
            return parseIdentityText(req, res, next)
        }
        if (!req.body) {
            req.body = {}
        }
        if (mediaTypeOf(req) !== TEXT_MEDIA_TYPE || req.headers['content-length'] === '0' || !readsBody(req)) {
            return next()
        }
        if (!decompressorFor(encoding)) {
            return refuse(res, 415, 'Unsupported content encoding')
        }
        if (Number(req.headers['content-length'] ?? 0) > DEFAULT_TEXT_PARSER_LIMIT_BYTES) {
            return refuse(res, 413, 'Request entity too large')
        }
        readBody(req, res, (error, decoded) => {
            if (error) {
                return (error as Error).message === 'Request entity too large'
                    ? refuse(res, 413, 'Request entity too large')
                    : next(error)
            }
            if (!decoded!.ok) {
                return decoded!.status === 413
                    ? refuse(res, 413, 'Request entity too large')
                    : refuse(res, 400, 'Malformed compressed body')
            }
            if (decoded!.bytes.length === 0) {
                return next()
            }
            const charset = charsetOf(req)
            if (!TEXT_CHARSETS.has(charset)) {
                return refuse(res, 415, 'Unsupported charset')
            }
            req.body = decoded!.bytes.toString(charset as BufferEncoding)
            next()
        })
    }
}
