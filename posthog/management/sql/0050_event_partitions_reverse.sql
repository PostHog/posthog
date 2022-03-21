DROP FUNCTION update_partitions;
DROP FUNCTION create_partitions;

ALTER TABLE posthog_event rename to old_posthog_event;
CREATE TABLE posthog_event (like old_posthog_event including defaults);

ALTER SEQUENCE posthog_event_id_seq OWNED BY posthog_event."id";

INSERT INTO public.posthog_event (id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash)
SELECT id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash
FROM public.old_posthog_event;

DROP TABLE old_posthog_event CASCADE;
DROP TABLE posthog_event_partitions_manifest CASCADE;

ALTER TABLE posthog_action_events DROP COLUMN timestamp, DROP COLUMN event;
ALTER TABLE posthog_element DROP COLUMN timestamp, DROP COLUMN event;

CREATE UNIQUE INDEX posthog_event_pkey ON public.posthog_event USING btree (id);
CREATE INDEX posthog_event_team_id_a8b4c6dc ON public.posthog_event USING btree (team_id);
CREATE INDEX posthog_event_idx_distinct_id ON public.posthog_event USING btree (distinct_id);
CREATE INDEX posthog_eve_element_48becd_idx ON public.posthog_event USING btree (elements_hash);
CREATE INDEX posthog_eve_timesta_1f6a8c_idx ON public.posthog_event USING btree ("timestamp", team_id, event);
ALTER TABLE posthog_event ADD CONSTRAINT posthog_event_team_id_a8b4c6dc_fk_posthog_team_id FOREIGN KEY (team_id) REFERENCES posthog_team(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE posthog_action_events ADD CONSTRAINT posthog_action_events_event_id_7077ea70_fk_posthog_event_id FOREIGN KEY (event_id) REFERENCES posthog_event(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE posthog_element ADD CONSTRAINT posthog_element_event_id_bb6549a0_fk_posthog_event_id FOREIGN KEY (event_id) REFERENCES posthog_event(id) DEFERRABLE INITIALLY DEFERRED;