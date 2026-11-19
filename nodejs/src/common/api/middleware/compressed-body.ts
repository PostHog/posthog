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

function mediaTypeOf(req: Request): string {
    return (req.headers['content-type'] ?? '').split(';')[0].trim().toLowerCase()
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

export function createCompressedBodyMiddleware(limitBytes: number): RequestHandler {
    const textLimitBytes = Math.min(limitBytes, DEFAULT_TEXT_PARSER_LIMIT_BYTES)
    const readRawJson = express.raw({ type: () => true, inflate: false, limit: bytesParserLimit(limitBytes) })
    const readRawText = express.raw({ type: () => true, inflate: false, limit: bytesParserLimit(textLimitBytes) })

    const decodeBody = async (
        req: Request,
        res: Response,
        next: NextFunction,
        decompress: Decompress,
        mediaType: string
    ) => {
        const isText = mediaType === TEXT_MEDIA_TYPE
        let decoded: Buffer
        try {
            decoded = await decompress(req.body, isText ? textLimitBytes : limitBytes)
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code === 'ERR_BUFFER_TOO_LARGE') {
                return next(tooLarge())
            }
            return refuse(res, 400, 'Malformed compressed body')
        }
        if (isText) {
            req.body = decoded.toString(charsetOf(req) as BufferEncoding)
            return next()
        }
        const text = decoded.toString('utf8')
        ;(req as Request & { rawBody?: string }).rawBody = text
        req.body = text.length === 0 ? {} : parseJSON(text)
        next()
    }

    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = contentEncodingOf(req)
        if (encoding === 'identity' || !readsBody(req)) {
            return next()
        }
        const decompress = decompressorFor(encoding)
        const mediaType = mediaTypeOf(req)
        if (!decompress || (mediaType !== JSON_MEDIA_TYPE && mediaType !== TEXT_MEDIA_TYPE)) {
            return refuse(res, 415, 'Unsupported content encoding')
        }
        if (mediaType === TEXT_MEDIA_TYPE && !TEXT_CHARSETS.has(charsetOf(req))) {
            return refuse(res, 415, 'Unsupported charset')
        }

        const readRawBody = mediaType === TEXT_MEDIA_TYPE ? readRawText : readRawJson
        readRawBody(
            req,
            res,
            onceOnly((readError) => {
                try {
                    if (readError) {
                        return next(readError)
                    }
                    if (!Buffer.isBuffer(req.body) || (req.body.length === 0 && mediaType === JSON_MEDIA_TYPE)) {
                        req.body = {}
                        return next()
                    }
                    decodeBody(req, res, next, decompress, mediaType).catch(next)
                } catch (error) {
                    next(error)
                }
            })
        )
    }
}
