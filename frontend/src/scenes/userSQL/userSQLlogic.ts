import { kea } from 'kea'

import type { userSQLlogicType } from './userSQLlogicType'
export const userSQLlogic = kea<userSQLlogicType>({
    path: ['scenes', 'userSQL', 'userSQLlogic'],
})
