import { BuiltLogic, Logic, key } from 'kea'

export const tabAwareScene = <L extends Logic = Logic>() => {
    return (logic: BuiltLogic<L>) => {
        // add a tab-based key if none present
        key((props) => {
            if (!props.tabId) {
                throw new Error('Tab-aware scene logic must have a tabId prop')
            }
            return props.tabId
        })(logic)
    }
}
