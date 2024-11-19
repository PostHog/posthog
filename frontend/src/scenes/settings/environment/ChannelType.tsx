// /* eslint-disable @typescript-eslint/explicit-function-return-type */
// import { useActions, useValues } from 'kea'
// import { LemonButton } from 'lib/lemon-ui/LemonButton'
// import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
// import React, { useEffect, useRef, useState } from 'react'
// import { teamLogic } from 'scenes/teamLogic'
//
// import {
//     Active,
//     Announcements,
//     closestCenter,
//     CollisionDetection,
//     defaultDropAnimationSideEffects,
//     DndContext,
//     DragOverlay,
//     DropAnimation,
//     KeyboardCoordinateGetter,
//     KeyboardSensor,
//     MeasuringConfiguration,
//     Modifiers,
//     MouseSensor,
//     PointerActivationConstraint,
//     ScreenReaderInstructions,
//     TouchSensor,
//     UniqueIdentifier,
//     useSensor,
//     useSensors,
// } from '@dnd-kit/core'
// import {
//     AnimateLayoutChanges,
//     arrayMove,
//     NewIndexGetter,
//     rectSortingStrategy,
//     SortableContext,
//     sortableKeyboardCoordinates,
//     SortingStrategy,
//     useSortable,
//     verticalListSortingStrategy,
// } from '@dnd-kit/sortable'
//
// import { CustomChannelRule } from '~/queries/schema'
// import { LemonInput } from 'lib/lemon-ui/LemonInput'
// import { createPortal } from 'react-dom'
//
// import { Item, List, Wrapper } from '../../components'
// import React, { forwardRef } from 'react'
//
// export interface Props {
//     children: React.ReactNode
//     columns?: number
//     style?: React.CSSProperties
//     horizontal?: boolean
// }
//
// export const List = forwardRef<HTMLUListElement, Props>(({ children, columns = 1, horizontal, style }: Props, ref) => {
//     return <ul ref={ref}>{children}</ul>
// })
//
// export function createRange<T = number>(length: number, initializer: (index: number) => any = defaultInitializer): T[] {
//     return [...new Array(length)].map((_, index) => initializer(index))
// }
//
export function ChannelType(): JSX.Element {
    return <div />
    // const { updateCurrentTeam } = useActions(teamLogic)
    // const { currentTeam } = useValues(teamLogic)
    // const { reportCustomChannelTypeRulesUpdated } = useActions(eventUsageLogic)
    //
    // const savedCustomChannelTypeRules =
    //     currentTeam?.modifiers?.customChannelTypeRules ?? currentTeam?.default_modifiers?.customChannelTypeRules ?? null
    // const [customChannelTypeRules, setCustomChannelTypeRules] = useState<string>(
    //     savedCustomChannelTypeRules ? JSON.stringify(savedCustomChannelTypeRules) : ''
    // )
    //
    // const handleChange = (rules: string): void => {
    //     let parsed: CustomChannelRule[] = []
    //     try {
    //         parsed = JSON.parse(rules)
    //     } catch (e) {
    //         return
    //     }
    //
    //     updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, customChannelTypeRules: parsed } })
    //     reportCustomChannelTypeRulesUpdated(parsed.length)
    // }
    //
    // return (
    //     <>
    //         <p>Set your custom channel type</p>
    //         <LemonInput
    //             value={customChannelTypeRules}
    //             onChange={setCustomChannelTypeRules}
    //             placeholder="Enter JSON array of custom channel type rules"
    //         />
    //         <div className="mt-4">
    //             <LemonButton type="primary" onClick={() => handleChange(customChannelTypeRules)}>
    //                 Save
    //             </LemonButton>
    //         </div>
    //     </>
    // )
}
//
// export interface ChannelTypeCustomRulesProps {
//     customRules?: CustomChannelRule[] | null
//     setCustomRules: (customRules: CustomChannelRule[]) => void
// }
//
// export function ChannelTypeCustomRules({
//     customRules: _customRules,
//     setCustomRules: _setCustomRules,
// }: ChannelTypeCustomRulesProps): JSX.Element {
//     const customRules = _customRules != null ? _customRules : []
//     const [localCustomRules, setLocalCustomRules] = useState<CustomChannelRule[]>(customRules)
//
//     const updateCustomRules = (customRules: CustomChannelRule[]): void => {
//         setLocalCustomRules(customRules)
//         _setCustomRules(customRules)
//     }
//
//     const onAddFilter = (filter: CustomChannelRule): void => {
//         updateCustomRules([...customRules, filter])
//     }
//     const onEditFilter = (index: number, filter: CustomChannelRule): void => {
//         const newCustomRules = customRules.map((f, i) => {
//             if (i === index) {
//                 return filter
//             }
//             return f
//         })
//         updateCustomRules(newCustomRules)
//     }
//     const onRemoveFilter = (index: number): void => {
//         updateCustomRules(customRules.filter((_, i) => i !== index))
//     }
//
//     function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
//         function move(arr: CustomChannelRule[], from: number, to: number): CustomChannelRule[] {
//             const clone = [...arr]
//             Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
//             return clone.map((child, order) => ({ ...child, order }))
//         }
//         updateCustomRules(move(customRules, oldIndex, newIndex))
//     }
//
//     return (
//         <div className="flex flex-col gap-2">
//             <div className="flex items-center gap-2 flex-wrap">
//                 <Sortable strategy={verticalListSortingStrategy} />
//             </div>
//             <div>
//                 <button>Add</button>
//             </div>
//         </div>
//     )
// }
//
// export interface SortableProps {
//     activationConstraint?: PointerActivationConstraint
//     animateLayoutChanges?: AnimateLayoutChanges
//     adjustScale?: boolean
//     collisionDetection?: CollisionDetection
//     coordinateGetter?: KeyboardCoordinateGetter
//     Container?: any // To-do: Fix me
//     dropAnimation?: DropAnimation | null
//     getNewIndex?: NewIndexGetter
//     handle?: boolean
//     itemCount?: number
//     items?: UniqueIdentifier[]
//     measuring?: MeasuringConfiguration
//     modifiers?: Modifiers
//     renderItem?: any
//     removable?: boolean
//     reorderItems?: typeof arrayMove
//     strategy?: SortingStrategy
//     style?: React.CSSProperties
//     useDragOverlay?: boolean
//     getItemStyles?(args: {
//         id: UniqueIdentifier
//         index: number
//         isSorting: boolean
//         isDragOverlay: boolean
//         overIndex: number
//         isDragging: boolean
//     }): React.CSSProperties
//     wrapperStyle?(args: {
//         active: Pick<Active, 'id'> | null
//         index: number
//         isDragging: boolean
//         id: UniqueIdentifier
//     }): React.CSSProperties
//     isDisabled?(id: UniqueIdentifier): boolean
// }
//
// const dropAnimationConfig: DropAnimation = {
//     sideEffects: defaultDropAnimationSideEffects({
//         styles: {
//             active: {
//                 opacity: '0.5',
//             },
//         },
//     }),
// }
//
// const screenReaderInstructions: ScreenReaderInstructions = {
//     draggable: `
//     To pick up a sortable item, press the space bar.
//     While sorting, use the arrow keys to move the item.
//     Press space again to drop the item in its new position, or press escape to cancel.
//   `,
// }
//
// export function Sortable({
//     activationConstraint,
//     animateLayoutChanges,
//     adjustScale = false,
//     Container = List,
//     collisionDetection = closestCenter,
//     coordinateGetter = sortableKeyboardCoordinates,
//     dropAnimation = dropAnimationConfig,
//     getItemStyles = () => ({}),
//     getNewIndex,
//     handle = false,
//     itemCount = 16,
//     items: initialItems,
//     isDisabled = () => false,
//     measuring,
//     modifiers,
//     removable,
//     renderItem,
//     reorderItems = arrayMove,
//     strategy = rectSortingStrategy,
//     style,
//     useDragOverlay = true,
//     wrapperStyle = () => ({}),
// }: SortableProps): JSX.Element {
//     const [items, setItems] = useState<UniqueIdentifier[]>(
//         // @ts-expect-error
//         () => initialItems ?? createRange<UniqueIdentifier>(itemCount, (index) => index + 1)
//     )
//     const [activeId, setActiveId] = useState<UniqueIdentifier | null>(null)
//     const sensors = useSensors(
//         useSensor(MouseSensor, {
//             activationConstraint,
//         }),
//         useSensor(TouchSensor, {
//             activationConstraint,
//         }),
//         useSensor(KeyboardSensor, {
//             // Disable smooth scrolling in Cypress automated tests
//             scrollBehavior: 'Cypress' in window ? 'auto' : undefined,
//             coordinateGetter,
//         })
//     )
//     const isFirstAnnouncement = useRef(true)
//     const getIndex = (id: UniqueIdentifier) => items.indexOf(id)
//     const getPosition = (id: UniqueIdentifier) => getIndex(id) + 1
//     const activeIndex = activeId ? getIndex(activeId) : -1
//     const handleRemove = removable
//         ? (id: UniqueIdentifier) => setItems((items) => items.filter((item) => item !== id))
//         : undefined
//     const announcements: Announcements = {
//         onDragStart({ active: { id } }) {
//             return `Picked up sortable item ${String(id)}. Sortable item ${id} is in position ${getPosition(id)} of ${
//                 items.length
//             }`
//         },
//         onDragOver({ active, over }) {
//             // In this specific use-case, the picked up item's `id` is always the same as the first `over` id.
//             // The first `onDragOver` event therefore doesn't need to be announced, because it is called
//             // immediately after the `onDragStart` announcement and is redundant.
//             if (isFirstAnnouncement.current === true) {
//                 isFirstAnnouncement.current = false
//                 return
//             }
//
//             if (over) {
//                 return `Sortable item ${active.id} was moved into position ${getPosition(over.id)} of ${items.length}`
//             }
//
//             return
//         },
//         onDragEnd({ active, over }) {
//             if (over) {
//                 return `Sortable item ${active.id} was dropped at position ${getPosition(over.id)} of ${items.length}`
//             }
//
//             return
//         },
//         onDragCancel({ active: { id } }) {
//             return `Sorting was cancelled. Sortable item ${id} was dropped and returned to position ${getPosition(
//                 id
//             )} of ${items.length}.`
//         },
//     }
//
//     useEffect(() => {
//         if (!activeId) {
//             isFirstAnnouncement.current = true
//         }
//     }, [activeId])
//
//     return (
//         <DndContext
//             accessibility={{
//                 announcements,
//                 screenReaderInstructions,
//             }}
//             sensors={sensors}
//             collisionDetection={collisionDetection}
//             onDragStart={({ active }) => {
//                 if (!active) {
//                     return
//                 }
//
//                 setActiveId(active.id)
//             }}
//             onDragEnd={({ over }) => {
//                 setActiveId(null)
//
//                 if (over) {
//                     const overIndex = getIndex(over.id)
//                     if (activeIndex !== overIndex) {
//                         setItems((items) => reorderItems(items, activeIndex, overIndex))
//                     }
//                 }
//             }}
//             onDragCancel={() => setActiveId(null)}
//             measuring={measuring}
//             modifiers={modifiers}
//         >
//             <Wrapper style={style} center>
//                 <SortableContext items={items} strategy={strategy}>
//                     <Container>
//                         {items.map((value, index) => (
//                             <SortableItem
//                                 key={value}
//                                 id={value}
//                                 handle={handle}
//                                 index={index}
//                                 style={getItemStyles}
//                                 wrapperStyle={wrapperStyle}
//                                 disabled={isDisabled(value)}
//                                 renderItem={renderItem}
//                                 onRemove={handleRemove}
//                                 animateLayoutChanges={animateLayoutChanges}
//                                 useDragOverlay={useDragOverlay}
//                                 getNewIndex={getNewIndex}
//                             />
//                         ))}
//                     </Container>
//                 </SortableContext>
//             </Wrapper>
//             {useDragOverlay
//                 ? createPortal(
//                       <DragOverlay adjustScale={adjustScale} dropAnimation={dropAnimation}>
//                           {activeId ? (
//                               <Item
//                                   value={items[activeIndex]}
//                                   handle={handle}
//                                   renderItem={renderItem}
//                                   wrapperStyle={wrapperStyle({
//                                       active: { id: activeId },
//                                       index: activeIndex,
//                                       isDragging: true,
//                                       id: items[activeIndex],
//                                   })}
//                                   style={getItemStyles({
//                                       id: items[activeIndex],
//                                       index: activeIndex,
//                                       isSorting: activeId !== null,
//                                       isDragging: true,
//                                       overIndex: -1,
//                                       isDragOverlay: true,
//                                   })}
//                                   dragOverlay
//                               />
//                           ) : null}
//                       </DragOverlay>,
//                       document.body
//                   )
//                 : null}
//         </DndContext>
//     )
// }
//
// interface SortableItemProps {
//     animateLayoutChanges?: AnimateLayoutChanges
//     disabled?: boolean
//     getNewIndex?: NewIndexGetter
//     id: UniqueIdentifier
//     index: number
//     handle: boolean
//     useDragOverlay?: boolean
//     onRemove?(id: UniqueIdentifier): void
//     style(values: any): React.CSSProperties
//     renderItem?(args: any): React.ReactElement
//     wrapperStyle: SortableProps['wrapperStyle']
// }
//
// export function SortableItem({
//     disabled,
//     animateLayoutChanges,
//     getNewIndex,
//     handle,
//     id,
//     index,
//     onRemove,
//     style,
//     renderItem,
//     useDragOverlay,
//     wrapperStyle,
// }: SortableItemProps): JSX.Element {
//     const {
//         active,
//         attributes,
//         isDragging,
//         isSorting,
//         listeners,
//         overIndex,
//         setNodeRef,
//         setActivatorNodeRef,
//         transform,
//         transition,
//     } = useSortable({
//         id,
//         animateLayoutChanges,
//         disabled,
//         getNewIndex,
//     })
//
//     return (
//         <Item
//             ref={setNodeRef}
//             value={id}
//             disabled={disabled}
//             dragging={isDragging}
//             sorting={isSorting}
//             handle={handle}
//             handleProps={
//                 handle
//                     ? {
//                           ref: setActivatorNodeRef,
//                       }
//                     : undefined
//             }
//             renderItem={renderItem}
//             index={index}
//             style={style({
//                 index,
//                 id,
//                 isDragging,
//                 isSorting,
//                 overIndex,
//             })}
//             onRemove={onRemove ? () => onRemove(id) : undefined}
//             transform={transform}
//             transition={transition}
//             wrapperStyle={wrapperStyle?.({ index, isDragging, active, id })}
//             listeners={listeners}
//             data-index={index}
//             data-id={id}
//             dragOverlay={!useDragOverlay && isDragging}
//             {...attributes}
//         />
//     )
// }
//
//
// export interface Props {
//   dragOverlay?: boolean;
//   color?: string;
//   disabled?: boolean;
//   dragging?: boolean;
//   handle?: boolean;
//   handleProps?: any;
//   height?: number;
//   index?: number;
//   fadeIn?: boolean;
//   transform?: Transform | null;
//   listeners?: DraggableSyntheticListeners;
//   sorting?: boolean;
//   style?: React.CSSProperties;
//   transition?: string | null;
//   wrapperStyle?: React.CSSProperties;
//   value: React.ReactNode;
//   onRemove?(): void;
//   renderItem?(args: {
//     dragOverlay: boolean;
//     dragging: boolean;
//     sorting: boolean;
//     index: number | undefined;
//     fadeIn: boolean;
//     listeners: DraggableSyntheticListeners;
//     ref: React.Ref<HTMLElement>;
//     style: React.CSSProperties | undefined;
//     transform: Props['transform'];
//     transition: Props['transition'];
//     value: Props['value'];
//   }): React.ReactElement;
// }
//
// export const Item = React.memo(
//   React.forwardRef<HTMLLIElement, Props>(
//     (
//       {
//         color,
//         dragOverlay,
//         dragging,
//         disabled,
//         fadeIn,
//         handle,
//         handleProps,
//         height,
//         index,
//         listeners,
//         onRemove,
//         renderItem,
//         sorting,
//         style,
//         transition,
//         transform,
//         value,
//         wrapperStyle,
//         ...props
//       },
//       ref
//     ) => {
//       useEffect(() => {
//         if (!dragOverlay) {
//           return;
//         }
//
//         document.body.style.cursor = 'grabbing';
//
//         return () => {
//           document.body.style.cursor = '';
//         };
//       }, [dragOverlay]);
//
//       return renderItem ? (
//         renderItem({
//           dragOverlay: Boolean(dragOverlay),
//           dragging: Boolean(dragging),
//           sorting: Boolean(sorting),
//           index,
//           fadeIn: Boolean(fadeIn),
//           listeners,
//           ref,
//           style,
//           transform,
//           transition,
//           value,
//         })
//       ) : (
//         <li
//           className={classNames(
//             styles.Wrapper,
//             fadeIn && styles.fadeIn,
//             sorting && styles.sorting,
//             dragOverlay && styles.dragOverlay
//           )}
//           style={
//             {
//               ...wrapperStyle,
//               transition: [transition, wrapperStyle?.transition]
//                 .filter(Boolean)
//                 .join(', '),
//               '--translate-x': transform
//                 ? `${Math.round(transform.x)}px`
//                 : undefined,
//               '--translate-y': transform
//                 ? `${Math.round(transform.y)}px`
//                 : undefined,
//               '--scale-x': transform?.scaleX
//                 ? `${transform.scaleX}`
//                 : undefined,
//               '--scale-y': transform?.scaleY
//                 ? `${transform.scaleY}`
//                 : undefined,
//               '--index': index,
//               '--color': color,
//             } as React.CSSProperties
//           }
//           ref={ref}
//         >
//           <div
//             className={classNames(
//               styles.Item,
//               dragging && styles.dragging,
//               handle && styles.withHandle,
//               dragOverlay && styles.dragOverlay,
//               disabled && styles.disabled,
//               color && styles.color
//             )}
//             style={style}
//             data-cypress="draggable-item"
//             {...(!handle ? listeners : undefined)}
//             {...props}
//             tabIndex={!handle ? 0 : undefined}
//           >
//             {value}
//             <span className={styles.Actions}>
//               {onRemove ? (
//                 <Remove className={styles.Remove} onClick={onRemove} />
//               ) : null}
//               {handle ? <Handle {...handleProps} {...listeners} /> : null}
//             </span>
//           </div>
//         </li>
//       );
//     }
//   )
// );
