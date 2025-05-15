import { kea, path } from 'kea'

import type { chatLogicType } from './chatLogicType'

export const chatLogic = kea<chatLogicType>([path(['products', 'chat', 'frontend', 'chatLogic'])])
