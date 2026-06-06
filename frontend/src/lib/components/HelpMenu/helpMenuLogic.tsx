import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { healthSummaryLogic } from './healthSummaryLogic'
import type { helpMenuLogicType } from './helpMenuLogicType'

export type HelpBadgeStatus = 'danger' | 'warning' | 'success'

export const helpMenuLogic = kea<helpMenuLogicType>([
    path(['lib', 'components', 'HelpMenu', 'helpMenuLogic']),
    connect(() => ({
        values: [healthSummaryLogic, ['totalIssues', 'criticalCount', 'warningCount']],
    })),
    actions({
        setHelpMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleHelpMenu: true,
    }),
    reducers({
        isHelpMenuOpen: [
            false,
            {
                setHelpMenuOpen: (_, { isOpen }) => isOpen,
                toggleHelpMenu: (state) => !state,
            },
        ],
    }),
    selectors({
        hasHealthIssue: [(s) => [s.totalIssues], (totalIssues): boolean => totalIssues > 0],
        triggerBadgeContent: [(s) => [s.hasHealthIssue], (hasHealthIssue): string => (hasHealthIssue ? '!' : '')],
        triggerBadgeStatus: [
            (s) => [s.hasHealthIssue, s.criticalCount, s.warningCount],
            (hasHealthIssue, criticalCount, warningCount): HelpBadgeStatus => {
                if (!hasHealthIssue) {
                    return 'success'
                }
                if (criticalCount > 0) {
                    return 'danger'
                }
                if (warningCount > 0) {
                    return 'warning'
                }
                return 'success'
            },
        ],
    }),
])
