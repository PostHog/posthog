import ReactJson, { ReactJsonViewProps } from '@microlink/react-json-view'
import { useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function JSONViewer(props: ReactJsonViewProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <ReactJson // eslint-disable-line react/forbid-elements
            style={{ background: 'transparent' }}
            theme={isDarkModeOn ? 'railscasts' : 'rjv-default'}
            {...props}
        />
    )
}
