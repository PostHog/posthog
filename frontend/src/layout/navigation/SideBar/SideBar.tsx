import './SideBar.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NotebookPopover } from 'scenes/notebooks/NotebookPanel/NotebookPopover'

import { navigationLogic } from '../navigationLogic'

export function SideBar(): JSX.Element {
    const { isSideBarShown } = useValues(navigationLogic)

    return (
        <div className={clsx('SideBar', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__slider__content">
                    <DebugNotice />
                </div>
            </div>
            <NotebookPopover />
            <ActivationSidebar />
        </div>
    )
}
