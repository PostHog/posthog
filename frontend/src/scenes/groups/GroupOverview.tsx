import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { groupLogic } from 'scenes/groups/groupLogic'
export function GroupOverview(): JSX.Element {
    const { groupTypeName } = useValues(groupLogic)

    return (
        <div className="border-2 border-dashed border-primary w-full p-8 justify-center rounded mt-2 mb-4">
            <div className="flex items-center gap-8 w-full justify-center">
                <div className="flex-shrink max-w-140">
                    <h2>No {groupTypeName} dashboard yet</h2>
                    <p className="ml-0">
                        Create a standard dashboard to use with each {groupTypeName} to see weekly active users, most
                        used features, and more.
                    </p>
                    <div className="flex items-center gap-x-4 gap-y-2 mt-6">
                        <LemonButton type="primary" onClick={() => {}}>
                            Generate dashboard
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}
