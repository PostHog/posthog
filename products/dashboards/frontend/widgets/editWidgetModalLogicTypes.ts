export type ValidationResult = { success: true } | { success: false; fieldErrors: Record<string, string> }
