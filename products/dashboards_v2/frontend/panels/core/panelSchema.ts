import { z } from 'zod'

/** Which parts of a content tile show. A part that is missing shows. */
export const contentPanelPartsSchema = z.object({
    header: z.boolean().optional(),
    footer: z.boolean().optional(),
})

/** How a tile looks. A setting that is missing is on. A section has no background to change. */
export const tileAppearanceSchema = z.object({
    border: z.boolean().optional(),
    /** Any CSS color. The tile mixes it into its background as a tint, and `transparent` removes the background. */
    backgroundColor: z.string().min(1).optional(),
})

/**
 * The fields every content tile has. Everything specific to the panel type, such as a chart's query, sits in
 * `config`, which is checked against the type's own `configSchema`.
 */
export const contentPanelSchema = z.object({
    /** Names the panel type that renders it. The host supplies the types, so this is open, except for `section`. */
    type: z.string().refine((type) => type !== 'section', 'A section needs a title and tiles'),
    title: z.string().optional(),
    description: z.string().optional(),
    refreshedAt: z.iso.datetime({ offset: true }).optional(),
    parts: contentPanelPartsSchema.optional(),
    appearance: tileAppearanceSchema.optional(),
    config: z.unknown(),
    /** Set once the panel shows on more than one tile. Its content is then saved once, in the document's `panels`. */
    ref: z.string().min(1).optional(),
})

/** A panel shown on several tiles. Each tile chooses its own parts and appearance. */
export const sharedPanelSchema = contentPanelSchema.omit({ parts: true, appearance: true, ref: true })

export type ContentPanelParts = z.infer<typeof contentPanelPartsSchema>

export type TileAppearance = z.infer<typeof tileAppearanceSchema>

export type ContentPanel<Config> = Omit<z.infer<typeof contentPanelSchema>, 'config'> & { config: Config }

/** A panel as saved. Its `config` is checked against its type's `configSchema` before the type's own code uses it. */
export type SavedPanel = ContentPanel<z.infer<typeof contentPanelSchema>['config']>
