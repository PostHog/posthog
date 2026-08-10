import { BuiltLogic, afterMount } from 'kea'

/**
 * Some kea logics are used heavily across multiple areas so we keep it mounted once loaded with this trick.
 */
export function permanentlyMount(): (logic: BuiltLogic) => void {
    return (logic) => {
        afterMount(() => {
            // A keyed logic has one instance per key, so the re-entrant mount below would leak a
            // growing set of instances and has crashed React render in the past. Refuse it.
            if (logic.key !== undefined) {
                return
            }
            if (!logic.cache._permanentMount) {
                logic.cache._permanentMount = true
                logic.mount()
            }
        })(logic)
    }
}
