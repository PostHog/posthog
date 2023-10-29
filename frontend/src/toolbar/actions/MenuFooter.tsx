import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export const MenuFooter = (): JSX.Element => {
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="w-full text-right mt-4 pr-2">
            <a href={`${apiURL}${urls.actions()}`} target="_blank" rel="noopener noreferrer">
                View &amp; edit all actions <IconOpenInNew />
            </a>
        </div>
    )
}
