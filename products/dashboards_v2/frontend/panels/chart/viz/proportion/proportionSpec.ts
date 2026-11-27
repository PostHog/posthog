import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const proportionSpec: VizSpec<NoOptions> = {
    type: 'proportion',
    label: 'Proportion bar',
    // Six rows fit the title, the whole bar and its legend. Any shorter and the bar is cut off.
    size: { w: 12, h: 6, minW: 4, minH: 6 },
    optionsSchema: NO_OPTIONS,
}
