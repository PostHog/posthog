import { kea, path } from 'kea'

import type { exploreLogicType } from './exploreLogicType'

export const exploreLogic = kea<exploreLogicType>([path(['scenes', 'explore', 'exploreLogic'])])
