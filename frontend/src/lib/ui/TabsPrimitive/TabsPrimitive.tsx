import './TabsPrimitive.scss'

import * as Tabs from '@radix-ui/react-tabs'
import { cn } from 'lib/utils/css-classes'
import { useCallback, forwardRef, useRef, useState, useEffect, ElementRef, ComponentPropsWithoutRef, ComponentProps } from 'react';

export function TabsPrimitive({
    className,
    ...props
  }: ComponentProps<typeof Tabs.Root>) {
    return (
      <Tabs.Root
        data-slot="tabs"
        className={cn("flex flex-col", className)}
        {...props}
      />
    );
  }

export const TabsPrimitiveList = forwardRef<
  ElementRef<typeof Tabs.List>,
  ComponentPropsWithoutRef<typeof Tabs.List>
>(({ className, ...props }, ref) => {
  const [indicatorStyle, setIndicatorStyle] = useState({
    left: 0,
    width: 0,
    height: 0,
  });
  const tabsListRef = useRef<HTMLDivElement | null>(null);

  const updateIndicator = useCallback(() => {
    if (!tabsListRef.current) return;

    const activeTab = tabsListRef.current.querySelector<HTMLElement>(
      '[data-state="active"]'
    );
    if (!activeTab) return;

    const activeRect = activeTab.getBoundingClientRect();
    const tabsRect = tabsListRef.current.getBoundingClientRect();

    requestAnimationFrame(() => {
      setIndicatorStyle({
        left: activeRect.left - tabsRect.left,
        width: activeRect.width,
        height: activeRect.height,
      });
    });
  }, []);

  useEffect(() => {
    // Initial update
    const timeoutId = setTimeout(updateIndicator, 0);

    // Event listeners
    window.addEventListener("resize", updateIndicator);
    const observer = new MutationObserver(updateIndicator);

    if (tabsListRef.current) {
      observer.observe(tabsListRef.current, {
        attributes: true,
        childList: true,
        subtree: true,
      });
    }

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("resize", updateIndicator);
      observer.disconnect();
    };
  }, [updateIndicator]);

  return (
    <div className="relative" ref={tabsListRef}>
      <Tabs.List
        ref={ref}
        data-slot="tabs-list"
        className={cn(
          "relative inline-flex p-1 w-fit items-center justify-center gap-x-1",
          className
        )}
        {...props}
      />
      <div
        className="absolute bottom-0 h-[2px] bg-accent transition-all duration-300 ease-in-out"
        style={indicatorStyle}
      />
    </div>
  );
});

export const TabsPrimitiveTrigger = forwardRef<
  ElementRef<typeof Tabs.Trigger>,
  ComponentPropsWithoutRef<typeof Tabs.Trigger>
>(({ className, ...props }, ref) => (
  <Tabs.Trigger
    ref={ref}
    data-slot="tabs-trigger"
    className={cn(
      "data-[state=active]:text-accent focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:outline-ring inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-[3px] focus-visible:outline-1 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 z-10",
      className
    )}
    {...props}
  />
));

export interface TabsPrimitiveContentProps extends Tabs.TabsContentProps {}

export const TabsPrimitiveContent = forwardRef<
  ElementRef<typeof Tabs.Content>,
  ComponentPropsWithoutRef<typeof Tabs.Content>
>(({ className, ...props }, ref) => (
  <Tabs.Content
    ref={ref}
    data-slot="tabs-content"
    className={cn("flex-1 outline-none", className)}
    {...props}
  />
));
