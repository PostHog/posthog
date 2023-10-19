import { useActions, useValues } from 'kea'
import { inAppFeedbackLogic } from './inAppFeedbackLogic'

import { Query } from '~/queries/Query/Query'

export function InAppFeedback(): JSX.Element {
    const { dataTableQuery } = useValues(inAppFeedbackLogic)
    const { setDataTableQuery } = useActions(inAppFeedbackLogic)

    return <Query query={dataTableQuery} readOnly={true} setQuery={setDataTableQuery} />
}
