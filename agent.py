from cohere import Client

client = Client()

file = """
import React, { useCallback, useMemo } from 'react';
import { FlashList, ListRenderItem } from '@shopify/flash-list';
import { formatISO, isSameDay, subDays } from 'date-fns';
import { View } from 'react-native';
import { createStyleSheet, useStyles } from 'react-native-unistyles';

import { posthog } from '@dandapani/mobile/analytics';
import { useRitualCards, useRitualDays, useRituals } from '@dandapani/mobile/data';
import { Ritual, RitualCard, RitualDay } from '@dandapani/mobile/db';
import { CalendarTrigger, CalendarTriggerProps, useCalendarState } from '@dandapani/mobile/ui/calendar';
import { Placeholder } from '@dandapani/mobile/ui/placeholder';
import { RefreshControl } from '@dandapani/mobile/ui/refresh-control';
import { Text } from '@dandapani/mobile/ui/text';
import { RitualTimeBlock } from '@dandapani/shared/types';

import { HistoryCalendar } from '../components/history-calendar';
import { HistoryCard } from '../components/history-card';
import { HistoryCardSkeleton } from '../components/history-card-skeleton';
import { HistorySectionHeader } from '../components/history-section-header';

type ListItem =
  | {
      type: 'item';
      ritualCard: RitualCard;
      ritual?: Ritual;
      ritualDay?: RitualDay;
    }
  | {
      type: 'section';
      timeBlock: RitualTimeBlock;
    };

export const RitualHistory = React.memo(() => {
  const { calendarState, dispatch, measurePosition } = useCalendarState();
  const { styles } = useStyles(stylesheet);

  const openCalendar = useCallback(() => {
    dispatch({
      type: 'openCalendar',
    });
    posthog.capture('opened ritual calendar');
  }, [dispatch]);

  const formattedDate = useMemo(
    () =>
      formatISO(calendarState.selectedDate, {
        representation: 'date',
      }),
    [calendarState.selectedDate]
  );

  const { isLoading: isLoadingRitualCards, error: cardsError, data: ritualCards } = useRitualCards();
  const {
    isLoading: isLoadingRitualDays,
    error: daysError,
    refresh,
    isRefreshing,
    data: ritualDays,
  } = useRitualDays(formattedDate);
  const { isLoading: isLoadingRituals, error: ritualsError, data: rituals } = useRituals();

  const isLoading = isLoadingRitualCards || isLoadingRitualDays || isLoadingRituals;
  const isError = !!(cardsError || daysError || ritualsError);

  const data = useMemo(() => {
    const order = ritualCards.reduce((acc, card) => {
      const arr = acc.get(card.timeBlock);
      if (arr) {
        arr.push(card);
      } else {
        acc.set(card.timeBlock, [card]);
      }

      return acc;
    }, new Map<RitualTimeBlock, RitualCard[]>());

    const dayMap = new Map<RitualTimeBlock, Record<number, RitualDay>>();
    ritualDays.forEach((ritualDay) => {
      if (ritualDay.ritual && ritualDay.theme) {
        const nested = dayMap.get(ritualDay.ritual.timeBlock);
        if (nested) {
          nested[ritualDay.theme.id] = ritualDay;
        } else {
          dayMap.set(ritualDay.ritual.timeBlock, {
            [ritualDay.theme.id]: ritualDay,
          });
        }
      }
    });

    const ritualMap = new Map<RitualTimeBlock, Record<number, Ritual>>();
    rituals.forEach((ritual) => {
      const nested = ritualMap.get(ritual.timeBlock);
      if (nested) {
        nested[ritual.theme.id] = ritual;
      } else {
        ritualMap.set(ritual.timeBlock, {
          [ritual.theme.id]: ritual,
        });
      }
    });

    const items: ListItem[] = [];

    order.forEach((cards, timeBlock) => {
      items.push({
        type: 'section',
        timeBlock,
      });

      cards.forEach((card) => {
        const ritualDay = dayMap.get(timeBlock)?.[card.theme.id];

        items.push({
          type: 'item',
          ritualDay,
          ritual: ritualDay?.ritual || ritualMap.get(timeBlock)?.[card.theme.id],
          ritualCard: card,
        });
      });
    });

    return items;
  }, [ritualDays, ritualCards, rituals]);

  const extraData = useMemo(() => {
    const now = new Date();
    return {
      editable:
        isSameDay(subDays(now, 1), calendarState.selectedDate) ||
        isSameDay(subDays(now, 2), calendarState.selectedDate) ||
        isSameDay(now, calendarState.selectedDate),
      selectedDate: formatISO(calendarState.selectedDate, {
        representation: 'date',
      }),
    };
  }, [calendarState.selectedDate]);

  return (
    <>
      <FlashList
        data={isLoading ? undefined : data}
        keyExtractor={extractKey}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <ListHeader date={calendarState.selectedDate} openCalendar={openCalendar} measurePosition={measurePosition} />
        }
        ItemSeparatorComponent={ListSeparator}
        ListEmptyComponent={<ListPlaceholder isLoading={isLoading} isError={isError} />}
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refresh} />}
        estimatedItemSize={76}
        extraData={extraData}
      />
      <HistoryCalendar calendarState={calendarState} dispatch={dispatch} />
    </>
  );
});

const renderItem: ListRenderItem<ListItem> = ({ item, extraData }) => {
  if (item.type === 'section') {
    return <HistorySectionHeader timeBlock={item.timeBlock} />;
  }

  return (
    <HistoryCard
      ritualCard={item.ritualCard}
      ritualDay={item.ritualDay}
      ritual={item.ritual}
      editable={extraData.editable}
      date={extraData.selectedDate}
    />
  );
};

const extractKey = (item: ListItem): string =>
  item.type === 'section' ? item.timeBlock.toString() : item.ritualCard._id.toString();

const ListHeader = React.memo(({ date, openCalendar, measurePosition }: CalendarTriggerProps) => {
  const { styles } = useStyles(stylesheet);

  return (
    <View style={styles.header}>
      <Text>Date</Text>
      <CalendarTrigger date={date} openCalendar={openCalendar} measurePosition={measurePosition} />
    </View>
  );
});

const ListSeparator = React.memo(() => {
  return <View style={{ height: 16 }} />;
});

const ListPlaceholder = React.memo(({ isLoading, isError }: { isLoading: boolean; isError: boolean }) => {
  const { styles } = useStyles(stylesheet);

  if (isError) {
    return <Placeholder style={styles.placeholderContent} />;
  }

  return (
    <View style={styles.placeholder}>
      <HistorySectionHeader timeBlock={RitualTimeBlock.Morning} />
      <HistoryCardSkeleton />
      <HistoryCardSkeleton />
      <HistoryCardSkeleton />
      <HistorySectionHeader timeBlock={RitualTimeBlock.Day} />
      <HistoryCardSkeleton />
      <HistoryCardSkeleton />
      <HistoryCardSkeleton />
    </View>
  );
});

const stylesheet = createStyleSheet((theme, runtime) => ({
  container: {
    flex: 1,
  },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing[4],
    justifyContent: 'space-between',
  },

  list: {
    padding: theme.spacing[4],
    paddingBottom: theme.spacing[4] + runtime.insets.bottom + theme.floatingPlayerOffset,
  },

  placeholder: {
    gap: theme.spacing[4],
  },

  placeholderContent: {
    marginTop: theme.spacing[16],
  },
}));
"""
