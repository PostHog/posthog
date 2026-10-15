import { AttachmentPart, toAttachment } from './toAttachment'

const BLOB_HASH = 'a'.repeat(64)

describe('toAttachment', () => {
    it.each<[string, Record<string, unknown> & { type: string }, Omit<AttachmentPart, 'kind'>]>([
        [
            'an OpenAI image_url',
            { type: 'image_url', image_url: { url: 'https://cdn.example.com/receipt.png' } },
            { mediaType: 'image', name: null, mimeType: null, url: 'https://cdn.example.com/receipt.png' },
        ],
        [
            'an OpenAI input_audio with raw base64',
            { type: 'input_audio', input_audio: { data: 'UklGRg==', format: 'wav' } },
            { mediaType: 'audio', name: null, mimeType: 'audio/wav', url: 'data:audio/wav;base64,UklGRg==' },
        ],
        [
            'an OpenAI file with a filename',
            { type: 'file', file: { file_data: 'data:application/pdf;base64,JVBERi0=', filename: 'quote.pdf' } },
            {
                mediaType: 'file',
                name: 'quote.pdf',
                mimeType: 'application/pdf',
                url: 'data:application/pdf;base64,JVBERi0=',
            },
        ],
        [
            'an Anthropic base64 image',
            { type: 'image', source: { type: 'base64', media_type: 'image/png', data: 'iVBORw0=' } },
            { mediaType: 'image', name: null, mimeType: 'image/png', url: 'data:image/png;base64,iVBORw0=' },
        ],
        [
            'an Anthropic document',
            { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: 'JVBERi0=' } },
            {
                mediaType: 'file',
                name: null,
                mimeType: 'application/pdf',
                url: 'data:application/pdf;base64,JVBERi0=',
            },
        ],
        [
            'a Vercel file part whose mime type says it is an image',
            { type: 'file', mediaType: 'image/jpeg', file: 'https://cdn.example.com/latte.jpg' },
            { mediaType: 'image', name: null, mimeType: 'image/jpeg', url: 'https://cdn.example.com/latte.jpg' },
        ],
        [
            'a file part with an unresolvable upload reference',
            { type: 'file', mediaType: 'image/png', file: 'upload://screen-01' },
            { mediaType: 'image', name: null, mimeType: 'image/png', url: null },
        ],
        [
            'Gemini audio stored as a blob pointer',
            { type: 'audio', mime_type: 'audio/wav', data: `phaiblob://v1/sha256/${BLOB_HASH}?mime=audio/wav` },
            {
                mediaType: 'audio',
                name: null,
                mimeType: 'audio/wav',
                url: `/api/projects/7/ai_blob/v1/sha256/${BLOB_HASH}`,
            },
        ],
        [
            'a Gemini inline_data image',
            { type: 'image', inline_data: { mime_type: 'image/webp', data: 'UklGRg==' } },
            { mediaType: 'image', name: null, mimeType: 'image/webp', url: 'data:image/webp;base64,UklGRg==' },
        ],
        [
            'a Gemini inlineData document sent as an image part',
            { type: 'image', inlineData: { mimeType: 'application/pdf', data: 'JVBERi0=' } },
            {
                mediaType: 'file',
                name: null,
                mimeType: 'application/pdf',
                url: 'data:application/pdf;base64,JVBERi0=',
            },
        ],
        [
            'an image whose payload the SDK redacted',
            { type: 'image', source: { type: 'base64', media_type: 'image/png', data: '[base64 image redacted]' } },
            { mediaType: 'image', name: null, mimeType: 'image/png', url: null },
        ],
    ])('maps %s', (_name, item, expected) => {
        expect(toAttachment(item, 7)).toEqual({ kind: 'attachment', ...expected })
    })
})
