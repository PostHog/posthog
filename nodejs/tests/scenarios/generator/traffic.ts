import { z } from 'zod'

import type { TrafficDefinition } from '../cards/definitions'

export const eventEmail: TrafficDefinition = {
    name: 'event_email',
    params: z.object({}).strict(),
    profile: z.object({ ratePerSecond: z.number().positive() }).strict(),
}
