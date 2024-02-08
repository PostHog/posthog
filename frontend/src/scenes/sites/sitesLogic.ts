import { kea, path, selectors } from 'kea'

import { siteLogicType } from './sitesLogicType'

export const sitesLogic = kea<siteLogicType>([path(['scenes', 'sites', 'sitesLogic']), selectors({})])
