import { useValues } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import { DesktopBetaTermsSwitch } from './DesktopBetaTermsSwitch'

export function OrganizationDesktopBetaTerms(): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)
    if (currentProjectId === null) {
        return null
    }
    return <DesktopBetaTermsSwitch projectId={String(currentProjectId)} />
}
