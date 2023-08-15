import { Card } from 'antd'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function PluginLoading(): JSX.Element {
    return (
        <>
            {[1, 2, 3].map((i) => (
                <div className="plugins-scene-plugin-card-col w-full mb-2" key={i}>
                    {/* <Col key={i} style={{ marginBottom: 20, width: '100%' }} className="plugins-scene-plugin-card-col"> */}
                    <Card className="plugins-scene-plugin-card">
                        <div className="flex plugin-card-row items-center space-x-4">
                            <LemonSkeleton.Square />
                            <div className="flex flex-1 flex-col space-y-4">
                                <LemonSkeleton />
                                <LemonSkeleton className="w-1/2" />
                            </div>
                            <div>
                                <span className="show-over-500">
                                    <LemonSkeleton.Button size="small" className="w-30" />
                                </span>
                                <span className="hide-over-500">
                                    <LemonSkeleton.Button size="small" className="w-16" />
                                </span>
                            </div>
                        </div>
                    </Card>
                </div>
            ))}
        </>
    )
}
