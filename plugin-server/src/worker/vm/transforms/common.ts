import { PluginObj } from '@babel/core'
import * as types from '@babel/types'

import { Hub } from '../../../types'

export type PluginGen = (server: Hub, ...args: any[]) => (param: { types: typeof types }) => PluginObj
