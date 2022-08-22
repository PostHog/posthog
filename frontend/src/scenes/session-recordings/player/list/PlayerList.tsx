// import React, {useCallback, useEffect, useRef} from "react";
// import {List} from "react-virtualized";
// import {useActions, useValues} from "kea";
// import {SessionRecordingTab} from "~/types";
// import {listLogic} from "scenes/session-recordings/player/list/listLogic";
// import {sessionRecordingLogic} from "scenes/session-recordings/sessionRecordingLogic";
// import {ListRowProps} from "react-virtualized/dist/es/List";
// import {PropertyKeyInfo} from "lib/components/PropertyKeyInfo";
// import {Col, Row, Skeleton} from "antd";
// import clsx from "clsx";
// import {Tooltip} from "lib/components/Tooltip";
// import {InfoCircleOutlined} from "@ant-design/icons";
//
// export interface PlayerListProps {
//     tab: SessionRecordingTab
// }
//
// export function PlayerList({tab}: PlayerListProps): JSX.Element {
//     const listRef = useRef<List>(null)
//     const logic = listLogic({tab})
//     const {
//         data,
//         currentBoxSizeAndPosition,
//         showPositionFinder,
//         isRowIndexRendered,
//         isCurrent,
//         isDirectionUp,
//         renderedRows,
//     } = useValues(logic)
//     const {setRenderedRows, setList, scrollTo, disablePositionFinder, handleRowClick} = useActions(logic)
//     const {sessionEventsDataLoading} = useValues(sessionRecordingLogic)
//
//     useEffect(() => {
//         if (listRef?.current) {
//             setList(listRef.current)
//         }
//     }, [listRef.current])
//
//     const rowRenderer = useCallback(
//         function _rowRenderer({ index, style, key }: ListRowProps): JSX.Element {
//             const datum = data[index]
//             const _isCurrent = isCurrent(index)
//
//             return (
//                 <Row
//                     key={key}
//                     className={clsx('PlayerList__item', { 'PlayerList__item--current': _isCurrent })}
//                     align="top"
//                     style={{ ...style, zIndex: data.length - index }}
//                     onClick={() => {
//                         datum.playerPosition && handleRowClick(datum.playerPosition)
//                     }}
//                     data-tooltip="recording-player-list"
//                 >
//                     <Col className="PlayerList__item__icon">
//                         <div className="PlayerList__item__icon__wrapper">{renderIcon(event)}</div>
//                     </Col>
//                     <Col className={clsx('PlayerList__item__content', {
//                             'PlayerList__item__content--rendering': !isRowIndexRendered(index),
//                             'PlayerList__item__content--out-of-band': datum.isOutOfBand,
//                         })}
//                     >
//                         <Row className="PlayerList__item__content__top-row">
//                             <div>
//                                 <PropertyKeyInfo
//                                     className="PlayerList__item__content__title"
//                                     value={datum.event}
//                                     disableIcon
//                                     disablePopover
//                                     ellipsis={true}
//                                     style={{ maxWidth: 150 }}
//                                 />
//                                 {datum.isOutOfBand && (
//                                     <Tooltip
//                                         className="out-of-band-tooltip"
//                                         title={
//                                             <>
//                                                 <b>Out of band event</b>
//                                                 <p>
//                                                     This event originated from a different client library than this
//                                                     recording. As a result, it's timing and placement might not be
//                                                     precise.
//                                                 </p>
//                                             </>
//                                         }
//                                     >
//                                         <InfoCircleOutlined />
//                                     </Tooltip>
//                                 )}
//                             </div>
//                             <span className="event-item-content-timestamp">{datum.colonTimestamp}</span>
//                         </Row>
//                         {/*{hasDescription && (*/}
//                         {/*    <EventDescription description={capitalizeFirstLetter(eventToDescription(event, true))} />*/}
//                         {/*)}*/}
//                         <Skeleton active paragraph={{ rows: 2, width: ['40%', '100%'] }} title={false} />
//                     </Col>
//                 </Row>
//             )
//         },
//         [
//             data.length,
//             renderedRows.startIndex,
//             renderedRows.stopIndex,
//             currentBoxSizeAndPosition.top,
//             currentBoxSizeAndPosition.height,
//         ]
//     )
//
//     return (
//         <></>
//     )
// }
