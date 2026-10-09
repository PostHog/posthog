import { NewRunButton } from '../components/NewRunButton'
import { NewRunModal } from '../components/NewRunModal'

/**
 * The primary action of the empty state. The empty state renders in place of the runs scene, so the
 * modal that the scene mounts is not on the page, and this component mounts it with the button.
 */
export function StartFirstRunButton(): JSX.Element {
    return (
        <div className="self-start">
            <NewRunButton label="Start a run" />
            <NewRunModal />
        </div>
    )
}
