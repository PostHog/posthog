import { PluginObj } from '@babel/core'
import * as types from '@babel/types'

import { LegacyPluginHub } from '../../types'

export type PluginGen = (server: LegacyPluginHub, ...args: any[]) => (param: { types: typeof types }) => PluginObj
