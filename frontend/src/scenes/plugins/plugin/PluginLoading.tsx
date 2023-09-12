import { Skeleton } from 'antd'

export function PluginLoading(): JSX.Element {
    return (
        <div className="space-y-5">
            {[1, 2, 3].map((i) => (
                <div key={i} className="w-full">
                    <div className="border rounded plugins-scene-plugin-card">
                        <div className="flex items-center p-4 space-x-4">
                            <div className="hide-plugin-image-below-500">
                                <Skeleton.Avatar active size="large" shape="square" />
                            </div>
                            <div className="flex-1">
                                <Skeleton title={false} paragraph={{ rows: 2 }} active />
                            </div>
                            <div>
                                <span className="show-over-500">
                                    <Skeleton.Button style={{ width: 100 }} />
                                </span>
                                <span className="hide-over-500">
                                    <Skeleton.Button style={{ width: 32 }} />
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            ))}
        </div>
    )
}
