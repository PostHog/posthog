import './ToolbarFeatures.scss'
import { IconFlag, IconGroupedEvents, IconHeatmap } from 'lib/components/icons'
import { SearchOutlined } from '@ant-design/icons'

interface FeatureHighlightProps {
    title: string
    caption: string
    icon: JSX.Element
}

function FeatureHighlight({ title, caption, icon }: FeatureHighlightProps): JSX.Element {
    return (
        <div className="fh-item flex items-center mt-4">
            <div className="fh-icon mr-4 text-muted-alt">{icon}</div>
            <div>
                <h4 className="mb-0 text-muted-alt">{title}</h4>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}

export function ToolbarFeatures(): JSX.Element {
    const features: FeatureHighlightProps[] = [
        {
            title: 'Heatmaps',
            caption: 'Understand where your users interact the most.',
            icon: <IconHeatmap />,
        },
        {
            title: 'Actions',
            caption: 'Create actions visually from elements in your website.',
            icon: <IconGroupedEvents />,
        },
        {
            title: 'Feature Flags',
            caption: 'Toggle feature flags on/off right on your app.',
            icon: <IconFlag />,
        },
        {
            title: 'Inspect',
            caption: 'Inspect clickable elements on your website.',
            icon: <SearchOutlined />,
        },
    ]
    return (
        <div className="ToolbarFeatures mt-8 mx-auto mb-0 flex flex-wrap items-center justify-center">
            {features.map((feature) => (
                <FeatureHighlight key={feature.title} {...feature} />
            ))}
        </div>
    )
}
