import { kea, path } from 'kea'

import type { chatListLogicType } from './chatListLogicType'

export const chatListLogic = kea<chatListLogicType>([path(['products', 'chat', 'frontend', 'chatListLogic'])])
