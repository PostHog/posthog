import { z } from 'zod'

/** Shared widget config fields inherited by all widget types. */
export const baseWidgetConfigSchema = z.object({
    filterTestAccounts: z.boolean().optional(),
})

export type BaseWidgetConfig = z.infer<typeof baseWidgetConfigSchema>

export function resolveWidgetFilterTestAccounts(
    configValue: boolean | undefined | null,
    projectDefault: boolean
): boolean {
    return configValue ?? projectDefault
}

// New widget types: add per-type schemas here — CONTRIBUTING.md
