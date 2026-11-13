import { z } from 'zod'

import { TRAFFIC } from '../generator/traffic'
import { INVARIANTS } from '../judge/invariants'
import { MEASUREMENTS } from '../judge/measurements'
import { VALVES } from '../valves/valves'

export type Definition = { name: string; params: z.ZodType }

export type TrafficDefinition = Definition & { profile: z.ZodType }

export type TargetedDefinition = Definition & { target: z.ZodType }

export type Definitions = {
    valves: TargetedDefinition[]
    traffic: TrafficDefinition[]
    invariants: Definition[]
    measurements: Definition[]
}

export const DEFINITIONS: Definitions = {
    valves: VALVES,
    traffic: TRAFFIC,
    invariants: INVARIANTS,
    measurements: MEASUREMENTS,
}
