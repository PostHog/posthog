import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'

import type { NewConnectionLogicType } from './NewConnectionLogicType'
import { ConnectionChoiceType } from './types'
import { mockConnectionChoices } from './mocks'
import { loaders } from 'kea-loaders'

interface NewConnectionLogicProps {
    id: string
}

export const NewConnectionLogic = kea<NewConnectionLogicType>([
    path(['scenes', 'cdp', 'NewConnectionLogic']),
    props({} as NewConnectionLogicProps),
    key((props) => props.id ?? 'default'),
    reducers({
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
    }),
    loaders({
        connectionChoices: [
            undefined as ConnectionChoiceType[] | undefined,
            {
                loadConnectionChoice: async () => {
                    const connectionChoices = await Promise.resolve(mockConnectionChoices)
                    return connectionChoices
                },
            },
        ],
    }),
    selectors({
        connectionChoice: [
            (s) => [s.connectionChoices, (_, props) => props.id],
            (connectionChoices, connectionChoiceId): ConnectionChoiceType | undefined => {
                return connectionChoices.find((connectionChoice) => connectionChoice.id === connectionChoiceId)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadConnectionChoice()
    }),
    // selectors({
    //     connectionChoice: [
    //         (s) => [s.connectionChoices],
    //         (connectionChoices, connectionChoiceId): ConnectionChoiceType | undefined => {
    //             debugger
    //             return connectionChoices.find((connectionChoice) => connectionChoice.id === connectionChoiceId)
    //         },
    //     ],
    // }),
])
