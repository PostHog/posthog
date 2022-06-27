import { kea, path } from 'kea'
import { forms } from 'kea-forms'

import type { embedModalLogicType } from './embedModalLogicType'

export const embedModalLogic = kea<embedModalLogicType>([
    path(['lib', 'components', 'EmbedModal', 'embedModalLogic']),
    forms({
        embedConfig: {},
    }),
])
