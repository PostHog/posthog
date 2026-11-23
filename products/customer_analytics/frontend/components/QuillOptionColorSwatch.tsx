import { useValues } from 'kea'

import { DataColorToken } from 'lib/colors'
import { dataThemeLogic } from 'lib/logic/dataThemeLogic'

export function QuillOptionColorSwatch({ colorToken }: { colorToken: DataColorToken }): JSX.Element {
    const { getColorFromToken } = useValues(dataThemeLogic)

    const color = getColorFromToken(null, colorToken)

    if (color == null) {
        return <span className="inline-block size-3.5 shrink-0 rounded-full border-2 border-border bg-muted" />
    }

    return (
        <span
            className="inline-block size-3.5 shrink-0 rounded-full border-2"
            // The option color comes from the project's data color theme, so it can't be a token.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ borderColor: color, backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)` }}
        />
    )
}
