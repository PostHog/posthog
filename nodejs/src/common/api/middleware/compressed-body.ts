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

function isJsonBody(req: Request): boolean {
    return (req.headers['content-type'] ?? '').split(';')[0].trim().toLowerCase() === 'application/json'
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
    const readRawBody = express.raw({ type: () => true, inflate: false, limit: bytesParserLimit(limitBytes) })

    const decodeJson = async (req: Request, res: Response, next: NextFunction, decompress: Decompress) => {
        let decoded: Buffer
        try {
            decoded = await decompress(req.body, limitBytes)
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code === 'ERR_BUFFER_TOO_LARGE') {
                return next(tooLarge())
            }
            return refuse(res, 400, 'Malformed compressed body')
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
        if (!decompress || !isJsonBody(req)) {
            return refuse(res, 415, 'Unsupported content encoding')
        }

        readRawBody(
            req,
            res,
            onceOnly((readError) => {
                try {
                    if (readError) {
                        return next(readError)
                    }
                    if (!Buffer.isBuffer(req.body) || req.body.length === 0) {
                        req.body = {}
                        return next()
                    }
                    decodeJson(req, res, next, decompress).catch(next)
                } catch (error) {
                    next(error)
                }
            })
        )
    }
}
