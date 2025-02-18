import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

// enum ErrorTrackingAlertTemplate {
//     IssueCreated = 'error-tracking-issue-created',
// }

// type ErrorTrackingAlert = { type: ErrorTrackingAlertTemplate; title: string; description: string }

// const ALERTS: ErrorTrackingAlert[] = [
//     {
//         type: ErrorTrackingAlertTemplate.IssueCreated,
//         title: 'Issue created',
//         description: 'Notify me when a new issue occurs',
//     },
// ]

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            // logicKey="error-tracking-alerts"
            type="internal_destination"
            subTemplateId="error-tracking"
            filters={{
                events: [
                    {
                        id: `$error_tracking_issue_created`,
                        type: 'events',
                    },
                ],
            }}
        />
    )

    // const logic = hogFunctionListLogic({
    //     type: 'internal_destination',
    //     forceFilters: { filters: { events: [{ id: '$error_tracking_issue_created' }] } },
    // })
    // const { hogFunctions } = useValues(logic)
    // const { loadHogFunctions, toggleEnabled } = useActions(logic)
    // const [activeKey, setActiveKey] = useState<ErrorTrackingAlertTemplate | undefined>(undefined)

    // useEffect(() => {
    //     loadHogFunctions()
    // }, [])

    // return (
    //     <LemonCollapse
    //         activeKey={activeKey}
    //         onChange={(k) => setActiveKey(k || undefined)}
    //         panels={ALERTS.map(({ type, title, description }) =>
    //             panel({
    //                 type,
    //                 title,
    //                 description,
    //                 hogFn: hogFunctions.find(({ template }) => template?.id === fullTemplateName(type)),
    //                 active: activeKey === type,
    //                 toggleFunction: toggleEnabled,
    //                 setActiveKey,
    //             })
    //         )}
    //     />
    // )
}

// const panel = ({
//     type,
//     title,
//     description,
//     hogFn,
//     active,
//     toggleFunction,
//     setActiveKey,
// }: ErrorTrackingAlert & {
//     hogFn?: HogFunctionType
//     active: boolean
//     toggleFunction: (hogFunction: HogFunctionType, enabled: boolean) => void
//     setActiveKey: (value: ErrorTrackingAlertTemplate | undefined) => void
// }): LemonCollapsePanel<ErrorTrackingAlertTemplate> => {
//     const props = hogFn ? { id: hogFn.id } : { id: null, templateId: fullTemplateName(type) }

//     return {
//         key: type,
//         header: (
//             <div className="flex flex-1 items-center justify-between">
//                 <div className="space-y-1">
//                     <div>{title}</div>
//                     <div className="text-muted text-xs">{description}</div>
//                 </div>
//                 <LemonSwitch
//                     checked={hogFn ? hogFn.enabled : active}
//                     onChange={(value, e) => {
//                         e.stopPropagation()
//                         hogFn ? toggleFunction(hogFn, value) : setActiveKey(value ? type : undefined)
//                     }}
//                 />
//             </div>
//         ),
//         className: 'p-0 pb-2',
//         content:
//             active || hogFn ? (
//                 <HogFunctionConfiguration
//                     {...props}
//                     displayOptions={{
//                         embedded: true,
//                         hidePageHeader: true,
//                         hideOverview: true,
//                         showFilters: false,
//                         showExpectedVolume: false,
//                         showTesting: false,
//                         canEditSource: false,
//                         showPersonsCount: false,
//                     }}
//                 />
//             ) : null,
//     }
// }

// const fullTemplateName = (type: ErrorTrackingAlert['type']): string => {
//     return 'template-slack-' + type
// }
