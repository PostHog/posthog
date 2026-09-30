/**
 * JSX-based panel tree builder.
 * Use these components to declaratively define panel layouts.
 *
 * Example:
 * <PanelGroupTree direction="horizontal" sizes={[75, 25]}>
 *   <PanelLeaf>
 *     <PanelTab id="logs">{logsContent}</PanelTab>
 *   </PanelLeaf>
 *   <PanelLeaf showTabs={false}>{content}</PanelLeaf>
 * </PanelGroupTree>
 */
