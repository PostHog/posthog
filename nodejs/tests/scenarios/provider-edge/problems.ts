import { z } from 'zod'

export function problemsOf(error: z.ZodError, root: string): string[] {
    return error.issues.map((issue) => `${issue.path.join('.') || root}: ${issue.message}`)
}
