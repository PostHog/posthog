import { Node, mergeAttributes, nodePasteRule } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'

export interface EmbedOptions {
    HTMLAttributes: Record<string, any>
}

export type EmbedProvider = 'youtube' | 'vimeo' | 'loom' | 'unknown'

export interface EmbedAttributes {
    src: string
    provider: EmbedProvider
    videoId: string
    width?: number
    aspectRatio?: number
}

const YOUTUBE_REGEX =
    /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/g
const VIMEO_REGEX = /(?:https?:\/\/)?(?:www\.)?(?:vimeo\.com\/|player\.vimeo\.com\/video\/)(\d+)/g
const LOOM_REGEX = /(?:https?:\/\/)?(?:www\.)?loom\.com\/(?:share|embed)\/([a-zA-Z0-9]+)/g

export function parseEmbedUrl(url: string): { provider: EmbedProvider; videoId: string; embedUrl: string } | null {
    const youtubeMatch = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/)
    if (youtubeMatch) {
        return {
            provider: 'youtube',
            videoId: youtubeMatch[1],
            embedUrl: `https://www.youtube.com/embed/${youtubeMatch[1]}`,
        }
    }

    const vimeoMatch = url.match(/(?:vimeo\.com\/|player\.vimeo\.com\/video\/)(\d+)/)
    if (vimeoMatch) {
        return {
            provider: 'vimeo',
            videoId: vimeoMatch[1],
            embedUrl: `https://player.vimeo.com/video/${vimeoMatch[1]}`,
        }
    }

    const loomMatch = url.match(/loom\.com\/(?:share|embed)\/([a-zA-Z0-9]+)/)
    if (loomMatch) {
        return {
            provider: 'loom',
            videoId: loomMatch[1],
            embedUrl: `https://www.loom.com/embed/${loomMatch[1]}`,
        }
    }

    return null
}

function EmbedNodeView({ node }: { node: { attrs: Record<string, any> } }): JSX.Element {
    const { src, provider } = node.attrs as EmbedAttributes
    const parsed = parseEmbedUrl(src)
    const embedUrl = parsed?.embedUrl

    return (
        <NodeViewWrapper className="embed-wrapper" data-provider={provider}>
            <div
                className="embed-container"
                style={{
                    position: 'relative',
                    width: '100%',
                    paddingBottom: '56.25%', // 16:9
                    backgroundColor: '#000',
                    borderRadius: '8px',
                    overflow: 'hidden',
                }}
            >
                <iframe
                    src={embedUrl}
                    style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100%',
                        border: 'none',
                    }}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                    referrerPolicy="origin"
                    sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"
                />
            </div>
        </NodeViewWrapper>
    )
}

export const EmbedExtension = Node.create<EmbedOptions>({
    name: 'embed',

    group: 'block',

    atom: true,

    addOptions() {
        return {
            HTMLAttributes: {},
        }
    },

    addAttributes() {
        return {
            src: {
                default: null,
            },
            provider: {
                default: 'unknown',
            },
            videoId: {
                default: null,
            },
            width: {
                default: null,
            },
            aspectRatio: {
                default: 16 / 9,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-embed]',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        const src = HTMLAttributes.src as string
        const parsed = parseEmbedUrl(src)
        const embedUrl = parsed?.embedUrl || src

        return [
            'div',
            mergeAttributes(this.options.HTMLAttributes, {
                class: 'ph-tour-embed',
                'data-provider': HTMLAttributes.provider,
            }),
            [
                'div',
                { class: 'ph-tour-embed-container' },
                [
                    'iframe',
                    {
                        src: embedUrl,
                        frameborder: '0',
                        allowfullscreen: 'true',
                        allow: 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture',
                        referrerpolicy: 'origin',
                        sandbox: 'allow-scripts allow-same-origin allow-popups allow-presentation',
                    },
                ],
            ],
        ]
    },

    addNodeView() {
        return ReactNodeViewRenderer(EmbedNodeView)
    },

    addCommands() {
        return {
            setEmbed:
                (options: { src: string }) =>
                ({ commands }) => {
                    const parsed = parseEmbedUrl(options.src)
                    if (!parsed) {
                        return false
                    }
                    return commands.insertContent({
                        type: this.name,
                        attrs: {
                            src: options.src,
                            provider: parsed.provider,
                            videoId: parsed.videoId,
                        },
                    })
                },
        }
    },

    addPasteRules() {
        return [
            nodePasteRule({
                find: YOUTUBE_REGEX,
                type: this.type,
                getAttributes: (match) => {
                    const parsed = parseEmbedUrl(match[0])
                    return parsed
                        ? {
                              src: match[0],
                              provider: parsed.provider,
                              videoId: parsed.videoId,
                          }
                        : null
                },
            }),
            nodePasteRule({
                find: VIMEO_REGEX,
                type: this.type,
                getAttributes: (match) => {
                    const parsed = parseEmbedUrl(match[0])
                    return parsed
                        ? {
                              src: match[0],
                              provider: parsed.provider,
                              videoId: parsed.videoId,
                          }
                        : null
                },
            }),
            nodePasteRule({
                find: LOOM_REGEX,
                type: this.type,
                getAttributes: (match) => {
                    const parsed = parseEmbedUrl(match[0])
                    return parsed
                        ? {
                              src: match[0],
                              provider: parsed.provider,
                              videoId: parsed.videoId,
                          }
                        : null
                },
            }),
        ]
    },
})

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        embed: {
            setEmbed: (options: { src: string }) => ReturnType
        }
    }
}
