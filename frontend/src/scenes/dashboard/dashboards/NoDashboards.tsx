import { useActions } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

export const NoDashboards = (): JSX.Element => {
    return (
        <div className="mt-4">
            <p>Create your first dashboard:</p>
            <div className="flex justify-center items-center gap-4">
                <Option
                    title="Empty"
                    description="Start with an empty dashboard"
                    template={{ name: 'New Dashboard', template: '' }}
                />
                <Option
                    title="App Default"
                    description="Start with recommended metrics for a web app"
                    template={{ name: 'Web App Dashboard', template: 'DEFAULT_APP' }}
                />
            </div>
        </div>
    )
}

const Option = ({
    title,
    description,
    template,
}: {
    title: string
    description: string
    template: { name: string; template: string }
}): JSX.Element => {
    const { addDashboard } = useActions(newDashboardLogic)

    const onClick = (): void => {
        addDashboard({
            name: template.name,
            useTemplate: template.template,
        })
    }

    return (
        <div
            onClick={onClick}
            className="DashboardTemplates__option bg-light w-80 space-y-2 flex flex-col items-center rounded border p-3 cursor-pointer bg-accent"
        >
            <div className="font-medium">{title}</div>
            <span className="flex flex-wrap text-xs text-muted font-medium">{description}</span>
        </div>
    )
}
