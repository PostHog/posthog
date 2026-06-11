import { getAppContext } from './utils/getAppContext'

export const isUserLoggedIn = (): boolean => !getAppContext()?.anonymous
