import Piscina from '@posthog/piscina'

import { PluginsServerConfig } from '../types'
export const makePiscina: (config: PluginsServerConfig) => Piscina
