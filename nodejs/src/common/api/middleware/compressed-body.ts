import express, { NextFunction, Request, RequestHandler, Response } from 'ultimate-express'
import { brotliDecompress, gunzip, inflate } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

type Decompress = (input: Buffer, maxOutputLength: number) => Promise<Buffer>

const promised =
    (
        decompress: (
            input: Buffer,
            options: { maxOutputLength: number },
            callback: (error: Error | null, result: Buffer) => void
        ) => void
    ): Decompress =>
    (input, maxOutputLength) =>
        new Promise((resolve, reject) =>
            decompress(input, { maxOutputLength }, (error, result) => (error ? reject(error) : resolve(result)))
        )

const DECOMPRESSORS: Record<string, Decompress> = {
    gzip: promised(gunzip),
    deflate: promised(inflate),
    br: promised(brotliDecompress),
}

function tooLarge(): Error {
    return Object.assign(new Error('Request entity too large'), { status: 413 })
}

function mediaTypeOf(req: Request): string {
    return (req.headers['content-type'] ?? '').split(';')[0].trim().toLowerCase()
}

// ultimate-express decodes a compressed body outside its error handling, and checks the size limit only after each
// chunk is decoded. The json and text parsers that run after this middleware see req.bodyRead and skip.
export function createCompressedBodyMiddleware(limitBytes: number): RequestHandler {
    // ultimate-express passes `limit` through bytes(), which formats a number as text such as '1KB' and then never
    // matches it. A numeric string parses back to the byte count.
    const readCompressed = express.raw({ type: () => true, inflate: false, limit: String(limitBytes) })

    return (req: Request, res: Response, next: NextFunction) => {
        const encoding = (req.headers['content-encoding'] ?? 'identity').trim().toLowerCase()
        if (encoding === 'identity') {
            return next()
        }

        // The raw parser can call back more than once: after each chunk past the limit, and again at the end.
        let settled = false
        readCompressed(req, res, (error?: unknown) => {
            if (settled) {
                return
            }
            settled = true
            if (error) {
                return next(error)
            }
            if (!Buffer.isBuffer(req.body)) {
                return next()
            }
            const decompress = DECOMPRESSORS[encoding]
            if (!decompress) {
                res.status(415).json({ status: 'error', error: 'Unsupported content encoding' })
                return
            }
            decompress(req.body, limitBytes).then(
                (decoded) => {
                    try {
                        setDecodedBody(req, decoded)
                    } catch (parseError) {
                        return next(parseError)
                    }
                    next()
                },
                (decodeError: NodeJS.ErrnoException) => {
                    if (decodeError.code === 'ERR_BUFFER_TOO_LARGE') {
                        return next(tooLarge())
                    }
                    res.status(400).json({ status: 'error', error: 'Malformed compressed body' })
                }
            )
        })
    }
}

function setDecodedBody(req: Request, decoded: Buffer): void {
    switch (mediaTypeOf(req)) {
        case 'application/json': {
            const text = decoded.toString('utf8')
            ;(req as Request & { rawBody?: string }).rawBody = text
            req.body = text.length === 0 ? {} : parseJSON(text)
            return
        }
        case 'text/plain':
            req.body = decoded.toString('utf8')
            return
        default:
            req.body = decoded
    }
}
