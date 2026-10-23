import { z } from 'zod'

// Django's bare-address grammar, so the worker takes every copy Django accepts and none that names a second recipient.
export const BareEmailAddressSchema = z
    .string()
    .regex(/^[^\s@"<>,;:()[\]\\]+@[^\s@"<>,;:()[\]\\]+\.[^\s@"<>,;:()[\]\\]+$/)
