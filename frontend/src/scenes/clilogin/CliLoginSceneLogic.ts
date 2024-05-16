import { kea, path } from 'kea'

import type { CliLoginSceneLogicType } from './CliLoginSceneLogicType'

export type CliLoginSceneLogicProps = {
    code: string
}

export const CliLoginSceneLogic = kea<CliLoginSceneLogicType>([path(['scenes', 'cli-login', 'CliLoginSceneLogic'])])
