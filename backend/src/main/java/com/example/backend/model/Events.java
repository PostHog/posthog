package com.example.backend.model;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

import jakarta.persistence.Entity;

/**
 * events
 */
public record Events(
        UUID uuid,
        String event,
        String properties,
        LocalDateTime timestamp,
        int team_id,
        String distinct_id,
        String elements_chain,
        LocalDateTime created_at,
        UUID person_id,
        LocalDateTime person_created_at,
        String person_properties,
        String group0_properties,
        String group1_properties,
        String group2_properties,
        String group3_properties,
        String group4_properties,
        LocalDateTime group0_created_at,
        LocalDateTime group1_created_at,
        LocalDateTime group2_created_at,
        LocalDateTime group3_created_at,
        LocalDateTime group4_created_at,
        PersonModeEnum person_mode,
        String $group_0,
        String $group_1,
        String $group_2,
        String $group_3,
        String $group_4,
        String $window_id,
        String $session_id,
        UUID $session_id_uuid,
        String elements_chain_href,
        String[] elements_chain_texts,
        String[] elements_chain_ids,
        ElementsChainEnum elements_chain_elements,
        Map<String, String> properties_group_custom,
        Map<String, String> properties_group_ai,
        Map<String, String> properties_group_feature_flags,
        Map<String, String> person_properties_map_custom,
        LocalDateTime _timestamp,
        int _offset,
        LocalDateTime inserted_at,
        Boolean is_deleted,
        String[] consumer_breadcrumbs) {

}
