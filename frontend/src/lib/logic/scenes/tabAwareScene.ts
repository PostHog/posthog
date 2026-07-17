import { BuiltLogic, Logic, key } from 'kea'

const warnedPaths = new Set<string>()

/**
 * Key a scene's root logic by the internal tab it renders in (`props.tabId`, supplied by
 * sceneLogic), so every open tab gets its own instance and scene state is per-tab.
 *
 * Callers that predate tab awareness may still build the logic without a tabId (e.g. a child
 * logic `connect`ing to the scene root bare). Those fall back to one shared `__no_tab__`
 * instance — the pre-tabs singleton behavior — instead of throwing, but they will NOT see the
 * per-tab instance the scene itself renders. Thread the tabId through instead; the
 * tab-awareness tracker (products/desktop/TAB_AWARENESS.md) lists known offenders.
 */
export const tabAwareScene = <L extends Logic = Logic>() => {
    return (logic: BuiltLogic<L>) => {
        // add a tab-based key if none present
        key((props) => {
            if (props.tabId) {
                return props.tabId
            }
            if (!warnedPaths.has(logic.pathString)) {
                warnedPaths.add(logic.pathString)
                console.warn(
                    `Tab-aware scene logic (${logic.pathString}) built without a tabId prop; ` +
                        `falling back to a shared instance. Thread the tabId through instead.`
                )
            }
            return '__no_tab__'
        })(logic)
    }
}
