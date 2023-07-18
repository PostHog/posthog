import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Map, Marker } from 'pigeon-maps'
import { useState } from 'react'
import { decodeGeohash } from 'scenes/insights/views/GeoMap/decodeGeohash'

export function GeoMap(): JSX.Element {
    const { insight } = useValues(insightLogic)
    const [center, setCenter] = useState([50.879, 4.6997] as [number, number])
    const [zoom, setZoom] = useState(1)

    return (
        <div className="relative">
            <Map
                height={500}
                center={center}
                zoom={zoom}
                onBoundsChanged={({ center, zoom }) => {
                    setCenter(center)
                    setZoom(zoom)
                }}
            >
                {insight.result?.map((row: any) => {
                    const point = decodeGeohash(String(row.breakdown_value))
                    return (
                        <Marker width={40} height={40} key={String(row.breakdown_value)} anchor={point}>
                            <div
                                className="flex items-center justify-center"
                                style={{
                                    zIndex: row.count,
                                    borderRadius: '100%',
                                    height: 40,
                                    width: 40,
                                    background: 'rgba(255,255,255,0.7)',
                                }}
                            >
                                {row.count}
                            </div>
                        </Marker>
                    )
                })}
            </Map>
        </div>
    )
}
