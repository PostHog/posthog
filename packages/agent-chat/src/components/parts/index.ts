/**
 * Shared rendering atoms for an assistant turn's parts. Both the live
 * dock (`<TurnRow>`) and the session playback (`<SessionPlayback>`)
 * compose these so new part kinds and design tweaks apply on both
 * surfaces.
 */

export { Labeled } from './Labeled'

export { PartRenderer } from './PartRenderer'
export type { ClientToolOutcome, PartRendererProps, PartTextVariant } from './PartRenderer'

export { ThinkingPart } from './ThinkingPart'

export { ToolCallCard } from './ToolCallCard'
export type { ToolCallCardProps } from './ToolCallCard'
