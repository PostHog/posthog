package com.example.backend.model;

import java.time.LocalDateTime;

import org.springframework.stereotype.Component;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * HeatmapQueryParams
 */
@Setter
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Component
public class HeatmapQueryParams {

    private String type;
    private LocalDateTime dateFrom;
    private String urlExact;
    private Integer viewportWidthMin;
    private Integer viewportWidthMax;
    private String aggregation;
    private String temporaryToken;

    public HeatmapQueryParams(String query) {
        String q = query.startsWith("?") ? query.substring(1) : query;

        for (String part : q.split("&")) {
            if (part.isEmpty())
                continue;
            int idx = part.indexOf('=');
            String key = idx >= 0 ? part.substring(0, idx) : part;
            String val = idx >= 0 ? part.substring(idx + 1) : "";

            switch (key) {
                case "type":
                    this.type = val;
                    break;
                case "date_from":
                    this.dateFrom = getTheDate(val);
                    break;
                case "url_exact":
                    this.urlExact = val.replace("%3A", ":");
                    this.urlExact = this.urlExact.replace("%2F", "/");
                    break;
                case "viewport_width_min":
                    this.viewportWidthMin = Integer.parseInt(val);
                    break;
                case "viewport_width_max":
                    this.viewportWidthMax = Integer.parseInt(val);
                    break;
                case "aggregation":
                    this.aggregation = val;
                    break;
                case "temporary_token":
                    this.temporaryToken = val;
                    break;
                default:
                    // ignore unknown keys or log them
            }
        }
    }

    private LocalDateTime getTheDate(String val) {
        char suf = val.charAt(val.length() - 1);
        int day;
        if (suf != 't') {
            day = Integer.parseInt(val.substring(0, val.length() - 2));
        } else {
            day = -1;
        }
        switch (suf) {
            case 'h':
                day = -1;
                break;
            case 'w':
                day *= 7;
                break;
            case 'm':
                day *= 30;
                break;
            case 'y':
                day *= 365;
                break;
        }
        return LocalDateTime.now().minusDays(day);
    }
}
