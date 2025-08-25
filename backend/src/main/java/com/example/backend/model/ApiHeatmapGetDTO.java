package com.example.backend.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * apiHeatmapGetDTO
 */
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Component
public class ApiHeatmapGetDTO {
    private int count;
    private int pointer_y;
    private float pointer_relative_x;
    private boolean pointer_target_fixed;

    public void setKeyMap(KeyMap key, Integer value) {
        this.pointer_relative_x = key.x;
        this.pointer_y = key.y;
        this.pointer_target_fixed = key.fixed;
        this.count = value;
    }
}

