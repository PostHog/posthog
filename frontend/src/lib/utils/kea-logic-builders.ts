import { BuiltLogic, afterMount } from 'kea'

/**
 * Some kea logics are used heavily across multiple areas so we keep it mounted once loaded with this trick.
 */
export function permanentlyMount(): (logic: BuiltLogic) => void {
    return (logic) => {
        afterMount(() => {
            if (!logic.cache._permanentMount) {
                logic.cache._permanentMount = true
                logic.wrapper.mount()
            }
        })(logic)
    }
}
