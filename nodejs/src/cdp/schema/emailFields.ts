import { z } from 'zod'

// One bare address with a dotted domain. Spaces, quotes, brackets and list separators are refused, so a copy never
// names a second recipient.
export const BareEmailAddressSchema = z
    .string()
    .regex(/^[^\s@"<>,;:()[\]\\]+@[^\s@"<>,;:()[\]\\]+\.[^\s@"<>,;:()[\]\\]+$/)
