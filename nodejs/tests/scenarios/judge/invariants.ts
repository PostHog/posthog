import { z } from 'zod'

import type { Definition } from '../cards/definitions'

export const atLeastOnce: Definition = {
    name: 'at_least_once',
    params: z.object({}).strict(),
}
